# ParaBank: everything learned about the target

Working notes on the application this project automates. Every claim below was
checked against a running container unless it says otherwise; where a fact came
from reading the source, it says so.

Upstream: [parasoft/parabank](https://github.com/parasoft/parabank) ·
[Docker Hub](https://hub.docker.com/r/parasoft/parabank)

---

## 1. What it is

Parasoft's demo bank, shipped so people have something to point testing tools at.

| | |
|---|---|
| Stack | Spring MVC + JSP on Tomcat 10.1.60, JDK 21 |
| Database | HSQLDB, **in-container**, no volume |
| Base image | Ubuntu 24.04 |
| Architecture | multi-arch; `linux/arm64` is native on Apple Silicon, no emulation |
| Size | ~250 MB |

## 2. Why this target

The brief asks for a surface where you cannot assume a clean DOM, and says to
bias toward an approach that survives one. ParaBank qualifies on its own merits
rather than by pretending:

- Server-rendered JSP. Every action is a form POST to a `.htm` endpoint.
- Table-based layout, `class="form2"`, `<td width="30%">`. No semantic structure.
- **Zero `data-testid` attributes.** Verified: `grep -c 'data-testid'` on the
  landing page returns 0.
- Session state in a rewritten URL (see §7), not just a cookie.
- Framed panels assembled from JSP includes (`leftmenu.jsp`, `topPanel.jsp`).

It also has a REST API, which is a trap worth naming: using it would dissolve
the exercise, whose entire premise is a bank app with no API worth integrating.
**The agent and the replay engine never touch it.** Tests use it as an oracle,
to check the automation read the right number off the screen — see §8.

## 3. Image tags: two tenants for free

Three tags exist upstream. Checked via the registry API:

| Tag | arm64 digest | |
|---|---|---|
| `latest` | `sha256:7f0a6ab7…89ed12` | same image as `baseline` |
| `baseline` | `sha256:7f0a6ab7…89ed12` | **tenant A** — where capabilities are recorded |
| `feature` | `sha256:30ade16a…b426c5` | **tenant B** — a genuinely different build |

`baseline` and `latest` are byte-identical; `feature` is a distinct image. That
gives a free, honest stand-in for the brief's §3.7 scenario — two institutions
running the same vendor product at different versions — without mocking anything.

Tenant B is behind a compose profile and off by default.

## 4. ⚠️ It boots with no database schema

The single most important thing to know.

ParaBank starts with **no tables at all**. `IndexController` attempts to create
them lazily when the landing page is first requested. That path is unreliable.
Observed on a fresh container:

```
20:13:26.633 [http-nio-8080-exec-1] WARN  IndexController - Database not yet initialized. Initializing...
20:13:36.847 [http-nio-8080-exec-2] WARN  IndexController - Database not yet initialized. Initializing...
20:13:47.093 [http-nio-8080-exec-4] WARN  IndexController - Database not yet initialized. Initializing...
   ... repeating every 10s, indefinitely ...
```

Every lookup failed throughout with:

```
org.hsqldb.HsqlException: user lacks privilege or object not found: ACCOUNT
  in statement [SELECT id, customer_id, type, balance FROM Account WHERE id = ?]
```

Two concurrent init attempts 0.8s apart on different threads (`exec-2`,
`exec-3`) suggest the lazy path races with itself under a polling healthcheck.

**Throughout all of this the app returned HTTP 200 and `docker compose ps`
reported `healthy`.** Liveness is not readiness here, and the gap is wide enough
to swallow a whole demo.

The dependable fix is an explicit `POST /parabank/db.htm` with `action=INIT`,
which completes in under a second. That is what `interfaceai env reset` does, and why
starting the app is two commands rather than one.

### Consequence for the project

`interfaceai.parabank.is_up()` and `is_seeded()` are deliberately separate functions.
`is_up()` asks whether Tomcat serves the landing page; `is_seeded()` asks
whether account 13344 is readable. Only the second one licenses a run.

## 5. The two database states

`db.htm` takes two actions, and **`CLEAN` is not a wipe**. It runs the app's own
`reset.sql`, which `DELETE`s every table and then re-inserts exactly one
customer and one account:

```sql
DELETE FROM Stock; DELETE FROM Company; DELETE FROM Positions;
DELETE FROM Transaction; DELETE FROM Account; DELETE FROM Customer;
DELETE FROM Sequence;
INSERT INTO Customer (id, first_name, ...) VALUES (12212, 'John', ...);
INSERT INTO Account VALUES (13344, 12212, 0, '5022.93');
```

Measured against the running app:

| Account | After `action=INIT` | After `action=CLEAN` |
|---|---|---|
| 13344 | `SAVINGS $1,231.10` | **`CHECKING $5,022.93`** |
| 54321 | `CHECKING $1,351.12` | `Could not find account #54321` |
| 99999 | `Could not find account #99999` | `Could not find account #99999` |

This one lever produces both of the failure classes the brief insists a replay
contract must separate:

- **Expected business outcome** — 54321 genuinely stopped existing. The caller
  needs to hear "no such account", not a stack trace.
- **Violated checkpoint** — 13344 still resolves, as a *different record*. A
  replay whose checkpoint is "did I find account 13344" passes here and hands a
  bank $5,022.93 labelled as a savings balance. The checkpoint has to assert the
  values, not the lookup.

That second case is the more valuable one, and it came free with the target.

## 6. Seed data (`action=INIT`)

Read from `src/main/resources/com/parasoft/parabank/dao/jdbc/sql/insert.sql` and
confirmed live. `AccountType` ordinals from `domain/Account.java`: `0=CHECKING`,
`1=SAVINGS`, `2=LOAN`.

**Customers**

| id | username | password | name |
|---|---|---|---|
| 12212 | `john` | `demo` | John Smith |
| 12323 | `parasoft` | `demo` | Bob Parasoft |

**Accounts**

| id | customer | type | balance | |
|---|---|---|---|---|
| 12345 | 12212 | CHECKING | -2,300.00 | overdrawn |
| 12456 | 12212 | CHECKING | 10.45 | below minimum |
| 12567 | 12212 | CHECKING | 100.00 | |
| 12678 | 12212 | SAVINGS | -100.00 | negative savings |
| 12789 | 12212 | CHECKING | 100.00 | |
| 12900 | 12212 | CHECKING | 0.00 | zero |
| 13011 | 12212 | CHECKING | 100.00 | |
| 13122 | 12212 | CHECKING | 1,100.00 | |
| 13233 | 12212 | CHECKING | 100.00 | |
| **13344** | 12212 | **SAVINGS** | **1,231.10** | the demo checkpoint |
| 54321 | 12212 | CHECKING | 1,351.12 | |
| 13455 | 12323 | CHECKING | 2,014.76 | other customer |

**Parameters**: `initialBalance` 515.50, `minimumBalance` 100.00,
`loanProvider` ws, `loanProcessor` funds, `loanProcessorThreshold` 20,
`accessmode` jdbc.

Useful ids: **13344** is the only account matching the brief's worked example
("read their current savings balance"). **99999** exists in no state, so it
drives the not-found branch without touching the database.

`minimumBalance = 100.00` is a free validation-error lever: transfer out of
12456 (10.45) and ParaBank rejects it with its own error, no injection needed.

## 7. ⚠️ `;jsessionid=` is rewritten into every URL

Every link the app renders looks like this:

```html
<a href="overview.htm;jsessionid=FA51A8F9911DECD38C44FB2805CADE8B">
<form name="login" action="login.htm;jsessionid=56C9AAB996BA6B3B319DCE7158103E4D" method="POST">
```

Servlet URL rewriting for session tracking. The consequences are direct:

- **A recorded href is not replayable.** The token changes every session, so an
  artifact that stores a raw URL as a locator breaks on the very next run.
- Any recorded URL must be canonicalised — strip `;jsessionid=<hex>` — before it
  is written into an artifact. This is the concrete instance of the brief's
  canonicalisation stretch goal, and it is not hypothetical here.
- It is also a good argument for not locating by URL at all where a visual or
  accessibility-tree target is available.

This is exactly the kind of legacy behaviour that makes the target worth using.

## 8. The surface

**Routes** (from `sitemap.htm`, `;jsessionid` stripped)

| Public | Authenticated |
|---|---|
| `index.htm` — landing + login | `overview.htm` — account list |
| `register.htm` | `transfer.htm` |
| `lookup.htm` — forgot login | `billpay.htm` |
| `about.htm`, `contact.htm` | `openaccount.htm` |
| `services.htm`, `sitemap.htm` | `requestloan.htm` |
| `admin.htm` — **unauthenticated** | `findtrans.htm`, `updateprofile.htm`, `logout.htm` |

**Login form** — the one place field names are stable and worth recording:

```html
<form name="login" action="login.htm" method="POST">
  <input type="text"     class="input" name="username"/>
  <input type="password" class="input" name="password"/>
```

Credentials `john` / `demo`.

**Admin page** (`admin.htm`, no auth required) is the control surface for known
states. From `webapp/WEB-INF/jsp/content/admin.jsp`:

| Endpoint | Field | Effect |
|---|---|---|
| `POST db.htm` | `action=INIT` | full fixtures — §6 |
| `POST db.htm` | `action=CLEAN` | minimal dataset — §5 |
| `POST jms.htm` | `shutdown=true\|false` | stop/start the loan-processor queue. **Untested.** |
| `POST admin.htm` | `accessMode=jdbc\|soap\|restxml\|restjson` | swap the data layer |
| `POST admin.htm` | `initialBalance`, `minimumBalance` | move the validation thresholds |
| `POST admin.htm` | `loanProvider`, `loanProcessor`, `loanProcessorThreshold` | loan behaviour |

Every failure mode this project demonstrates comes from this page. Nothing is
monkeypatched and there is no fault-injection proxy — the app misbehaves on its
own terms, which is the point.

**REST API** — `/parabank/services/bank/accounts/{id}`. Content negotiated:
`Accept: application/json` returns JSON, otherwise XML.

```
$ curl -s -H 'Accept: application/json' localhost:8080/parabank/services/bank/accounts/13344
{"id":13344,"customerId":12212,"type":"SAVINGS","balance":1231.10}

$ curl -s localhost:8080/parabank/services/bank/accounts/99999
Could not find account #99999
```

Note the not-found response is **plain text with HTTP 200**, not a 404 and not
JSON. Worth remembering before writing a status-code check against it.

Used as a test oracle only. See §2.

## 9. Ports

| Port | What | Needed? |
|---|---|---|
| 8080 | Web UI + REST/SOAP | yes |
| 61616 | ActiveMQ, loan processor JMS | only to poke the queue directly |
| 9001 | HSQLDB SQL endpoint | only to assert DB state out of band |

Tenant B maps these to 8081 / 61617 / 9002 on the host.

## 10. Gotchas, collected

1. **No schema on boot, and it serves 200 anyway.** §4. Seed explicitly.
2. **`CLEAN` is not a wipe.** §5. It swaps in a different record under the same id.
3. **`;jsessionid=` in every URL.** §7. Canonicalise before recording.
4. **Not-found is HTTP 200 + plain text.** §8. Status codes will not save you.
5. **`index.htm` can answer 302.** A healthcheck without `curl -L` passes on the
   redirect without ever seeing the page.
6. **No volume, by choice.** `docker compose down` is a factory reset. Good for
   determinism, and it means state does not survive a container recreate — a
   recreate drops you back to §4.
7. **`admin.htm` needs no authentication.** Convenient here; worth flagging as
   the kind of thing that is normal in a demo app and catastrophic in a real one.
8. **Cold start is ~15s** on an M1 to healthy, plus the seed POST.
9. **`docker compose down` ignores profiled services.** Tenant B sits behind the
   `tenant-b` profile, and plain `down` does not see it. Measured:

   ```
   $ docker compose down                    # after starting both
   Container parabank  Removed
   Network interfaceai_default  Error
   failed to remove network ... has active endpoints
   ```

   `parabank-b` kept running and held the network open. Tear down with the same
   profile you brought up with: `docker compose --profile tenant-b down`.

## 11. Open questions

- `jms.htm` has never been exercised. Stopping the queue should make
  `requestloan.htm` fail in an interesting way, but that is a guess.
- What actually differs between `baseline` and `feature`? The digests differ;
  the behavioural delta has not been diffed. It matters for the multi-tenant
  story and should be measured before that story is told.
- Whether `accessMode=restjson` changes the *rendered UI* or only the data path
  behind it. If the former, it is another drift lever.
