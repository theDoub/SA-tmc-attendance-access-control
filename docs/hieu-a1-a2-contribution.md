# Issue Analysis and QR Validation at Access Gates

## 1. Context and Requirements

The attendance and access control system uses QR codes displayed on employees’ smartphones. When an employee scans a QR code at a gate, the system validates the credential, evaluates access permissions, and sends a command to the turnstile controller. The confirmed entry or exit is then used to create an attendance event.

The architecture has two sides. The **Edge** is the processing unit located at a gate station, connected to the QR scanner and turnstile controller. The **Hub** is the central server that manages system data and receives events from gate stations. The Edge stores the information required for local processing so that a temporary loss of connectivity does not automatically stop gate operations.

Two issues require particular attention: connectivity loss during attendance transaction processing and the exposure of static QR codes. A static QR code contains fixed information that can be photographed and reused. The proposed mechanisms must maintain gate availability while preventing invalid credentials from being accepted and attendance events from being lost.

### 1.1. Functional Requirements

Functional requirements describe the operations the system must perform.

| Requirement Area | Relevant Behaviour |
|---|---|
| User and QR code management | Employees obtain and display personal QR credentials; the system verifies their authenticity before using the identity information |
| Gate station management | Stations receive scans, return access results, and continue local validation when the central server is unavailable |
| Attendance event recording | The system records timestamped entry and exit events, stores them locally during outages, and synchronizes them after reconnection |
| Monitoring and auditing | Processing outcomes, including rejected attempts, remain traceable for troubleshooting and investigation |

### 1.2. Quality Requirements and Evaluation Criteria

Quality requirements define the performance, reliability, and security expected when these operations are performed.

| Requirement | Description and Verification Criteria |
|---|---|
| Performance | A gate station must respond within 2 seconds under approximately 800 transactions in 30 minutes per factory. QR validation has a target of less than 50 milliseconds to leave time for other processing steps. Both QR validation and the complete station response must be measured separately |
| Reliability | Accepted attendance events must not be lost during normal operation or temporary connectivity interruptions. After synchronization, event identifiers and contents must be reconciled to detect missing or duplicate records |
| Auditability | Each processing attempt must have a correlation identifier, timestamp, and outcome. Rejections must include a reason code. Raw QR contents must not be written to logs |
| Security | QR credentials must be digitally signed and locally verifiable. Validation must check expiry, intended destination, and previous use while minimizing personal data in the token |
| Availability | Stations must process scans using locally available keys and access policies within approved limits, then transmit pending data when connectivity returns |

These criteria are evaluation targets. Passing the existing QR unit tests does not establish that all system requirements have been satisfied.

## 2. Connectivity Loss During Attendance Transaction Processing

### 2.1. Causes and Consequences

If every scan requires a Hub request to validate a credential or authorize access, a network interruption can prevent the station from responding even when the local devices remain operational. If an event is transmitted without first being stored at the Edge, the interruption can also cause attendance data loss.

Another failure occurs when the Hub stores an event but its acknowledgement is lost. The Edge cannot determine whether the event was accepted and must resend it. If the retry is treated as a new event, duplicate attendance records may be created.

### 2.2. Local Processing and Pending Event Storage

The Edge validates QR signatures using a locally supplied **public key**. A public key verifies signatures but cannot generate new ones. Access authorization uses a **local policy snapshot**, which is a stored set of rules describing which employees may use particular gates and under which conditions. These checks do not require a synchronous Hub request for every scan.

A local policy snapshot is considered fresh for 5 minutes after its last update. When the Hub is unreachable, an older snapshot may remain usable if its age does not exceed 2 hours, and decisions made using that snapshot must be marked accordingly. If the snapshot is older than 2 hours, missing, or corrupt, the station denies access and refers the case to the gate assistance procedure. This limit applies to access policy data, not to QR validity. An expired QR must still be rejected even when the policy snapshot remains usable.

Data durability is supported by a **Transactional Outbox**. This mechanism stores an attendance event and a corresponding pending-transmission entry in the same database transaction. The transaction is atomic: either both changes are committed or neither is retained. Consequently, a stored event cannot be omitted from the synchronization queue because of a partial write.

A background task reads pending entries and sends them to the Hub when connectivity is available. It operates separately from the gate decision path. `PENDING` means that an event is awaiting confirmation, whereas `SYNCED` means that the Hub has acknowledged its acceptance.

### 2.3. Distinguishing Processing Outcomes

Success at one stage does not imply success at the next stage.

| Stage | Meaning |
|---|---|
| Valid QR (`VALID`) | The credential has passed the implemented validation checks; the employee has not yet been authorized to use the gate |
| Access allowed (`ALLOW`) | The access policy permits an opening attempt; this does not establish that the gate opened or that the employee passed through |
| Unlock acknowledgement | The controller reports that it received or executed the command; this alone does not prove physical passage |
| Passage confirmation | Suitable device or sensor feedback indicates that passage occurred |
| Attendance recording | An attendance event is stored after the defined success condition is met |
| Synchronization acknowledgement | The Hub confirms acceptance of the event; this is separate from local persistence |

An **access attempt** records an attempted entry or exit, including rejected and failed attempts. An **attendance record** represents an attendance event. These must remain separate so that a scan or an authorization decision is not automatically counted as successful attendance.

The proposed processing sequence is:

```text
Scan QR → Validate credential → Evaluate access policy → Persist access attempt
        → Send unlock command → Confirm passage
        → Persist attendance event and outbox entry in one transaction
        → Synchronize in background → Receive Hub acknowledgement
```

This sequence is a proposed design rather than an integration flow already verified by the implementation. If the hardware does not expose passage sensors, a separate rule is required for handling controller acknowledgements alone. A command acknowledgement must not automatically be presented as evidence of physical passage.

### 2.4. Retrying Without Creating Duplicate Records

Each event receives a unique identifier when it is created. The same identifier is retained across all transmission attempts. The Hub checks this identifier before inserting a record. Receiving the same identifier with identical content should return a successful acknowledgement without creating another record. Receiving the same identifier with different content should produce a conflict rather than silently overwriting data or reporting successful synchronization.

This property is called **idempotency**: repeating the same request does not produce additional data effects beyond the first successful processing. An **ACK**, short for acknowledgement, identifies the events accepted by the Hub. The Edge marks only those events as `SYNCED`. Successful network transmission alone does not establish that the Hub stored the event.

### 2.5. Scenarios and Verification Criteria

| ID | Test Scenario | Expected Outcome and Verification |
|---|---|---|
| OFF-01 | Disconnect the network before a scan while the QR, public key, and access policy remain valid | QR validation makes no Hub request; the station evaluates access locally; verify that the access attempt is persisted before an unlock command is sent |
| OFF-02 | Lose connectivity after the attendance event and outbox entry have been committed | Both remain at the Edge; a failed transmission does not change the pending event to synchronized |
| OFF-03 | Store an event at the Hub, lose the acknowledgement, and let the Edge resend it | The event identifier remains unchanged and the Hub contains exactly one record; the Edge marks it synchronized only after receiving the appropriate acknowledgement |
| OFF-04 | Restore connectivity while multiple events are pending | Reconcile event identifiers and contents before and after synchronization; failure of one event must not cause other events to be lost |
| OFF-05 | Test policy snapshots aged 5 minutes, 2 hours, and more than 2 hours while offline | Apply the stated age limits; mark decisions using older data; deny access without unlocking when the limit is exceeded or the snapshot is missing or corrupt |
| OFF-06 | Inject a failure while persisting the access attempt | No unlock command is issued and successful attendance is not reported |
| OFF-07 | Inject a failure within the transaction that stores the attendance event and outbox entry | Roll back the entire transaction; no attendance event exists without its corresponding outbox entry |

These scenarios are integration verification criteria involving multiple components. Isolated QR unit tests do not demonstrate the storage, gate control, or synchronization behaviour described above.

## 3. Exposure and Misuse of Static QR Codes

### 3.1. Risk and Mitigation

A QR code containing a fixed employee identifier can be photographed and presented by another person. If the system only reads that identifier without checking its origin, validity period, and previous use, the copy can be accepted like the original.

The proposed solution uses a **token**, a package of credential data represented as a QR code. The token has a digital signature, a short validity period, and a unique identifier. **Asymmetric signatures** use two keys: a private key creates signatures and a public key verifies them. The private key remains at the Hub. The Edge holds only public keys, allowing it to detect modified data without gaining the ability to issue credentials.

| Mechanism | Benefit | Limitation |
|---|---|---|
| Digital signature verification | Detects modified token contents or signatures that do not match a trusted key | Does not prove that the person presenting the QR is its legitimate owner |
| Validity period checks | Reject expired tokens and reduce the time available to exploit a copied token | A copy may still be used before the token expires |
| Intended-destination check (`audience`) | Rejects a token intended for another station | The authorized station or group of stations must be defined and configured consistently |
| Previous-use check (`replay` protection) | Rejects a token already used within the replay-state scope | Protection applies only where stations can observe the same usage state |
| Local public-key verification | Avoids a Hub request for every scan | Stations still require a mechanism for receiving key updates and revocations |

These mechanisms reduce forgery and reuse risks but do not completely eliminate attendance fraud through shared QR images. A person holding a copy may use it before its owner while it remains valid. Scanners with independent usage stores may also accept the same token.

### 3.2. Proposed Token Issuance and Validation Flow

1. The employee signs in and authenticates with the Hub.
2. The Hub creates a token containing minimal identity information, its issuer, intended destination, issue time, expiry time, unique token identifier, and key version.
3. The Hub signs the token using its private key. The phone receives the token and displays it as a QR code.
4. The Edge receives the scanned contents, checks their structure, and locates the corresponding public key.
5. The Edge verifies the signature, trusted issuer, intended destination, validity period, and previous-use state.
6. If validation succeeds, the verified information is passed to the access policy component. Rejection must not lead to an unlock command.

This is a proposed issuance flow. Hub-side token issuance, signing, and the smartphone application are not implemented by the Edge validation simulation. If the phone cannot obtain a new token, the Edge must not extend an old token’s validity. Local verification during an Edge network outage does not imply that the phone can independently issue credentials while disconnected.

### 3.3. What the QR Code Provides to the Gate Station

The QR code provides a **signed credential token**, rather than a command to open the gate. The scanner reads the encoded string and forwards it to the Edge. The token supplies an employee reference, its issuer, its intended destination, its validity period, a unique token identifier, and the identifier of the verification key. It also carries a digital signature protecting those fields against modification.

An individual piece of information carried by the token is called a **claim**. The following claims are required by the current validator:

| Field | Meaning and Purpose |
|---|---|
| `sub` — subject | An employee reference; direct personal information such as a full name or identity document number should be avoided |
| `iss` — issuer | Identifies the token issuer so that the recipient can check its trusted origin; the simulation requires an exact match with the configured trusted issuer after signature verification |
| `aud` — audience | Identifies the station or scope allowed to receive the token; the simulation requires an exact match with the scanning station identifier |
| `jti` — token identifier | A unique token identifier used to recognize previous use |
| `kid` — key identifier | Identifies the public key or key version required for signature verification |
| `iat` — issued at | The token’s issue time |
| `exp` — expiration time | The instant at which the token ceases to be valid |

In the simulation, `iat` and `exp` are integers representing seconds since the Unix epoch in UTC, allowing consistent comparisons across machines. The `sub`, `iss`, `jti`, `kid`, and `aud` fields must be non-empty strings.


The **digital signature** accompanies the claims as a separate token part. The Edge uses `kid` to select a locally trusted public key and verifies that the signature matches the encoded claims. The QR does not supply the trusted public key or private signing key; accepting a key supplied by the QR itself would not establish that the issuer is trusted.

The station combines the token with information obtained independently:

| Information from the QR | Information Supplied by the Station | Processing Purpose |
|---|---|---|
| `iss`, `kid`, and signature | Configured trusted issuer and public-key mapping | Verify the token’s origin and integrity |
| `aud` | The station’s configured identifier | Check whether the token is intended for this station |
| `iat` and `exp` | The current timezone-aware validation time | Check whether the token is currently valid |
| `jti` | The local replay store | Check and record whether the token has already been used |
| Verified `sub` | Local access policy, gate identifier, direction, and time | Evaluate whether the employee may enter or exit at that gate |

After successful validation, the current implementation returns a `VerifiedCredential` containing the employee reference, token identifier, key version, issue time, and expiry time. The issuer and audience have been checked but are not additional fields in that return type. Rejected tokens do not produce a verified credential.

The QR does not contain the station’s access policy, grant access by itself, or prove physical passage. Access authorization, gate control, and attendance recording remain separate processing steps. Its contents are encoded rather than encrypted, so personal data should be minimized even though the token is signed.

### 3.4. Validation and Replay Protection Components

`QrValidator` is the validation interface. It receives the raw QR contents, station identifier, and current time, and returns a `QrValidationResult`. Only a `VALID` result carries a `VerifiedCredential`, which contains verified information for subsequent access authorization.

`ReplayGuard` is the interface for tracking previously used tokens. Its `check_and_record` operation checks whether a `jti` has already appeared and records its first use. These actions must be atomic: two simultaneous scans must not both observe an unused token and both accept it.

```python
validate(raw_payload: str, station_id: str, now: datetime) -> QrValidationResult
check_and_record(token_id: str, expires_at: datetime, now: datetime) -> bool
```

Here, `raw_payload` is the string read from the QR code, `station_id` identifies the station, `now` is the validation time, `token_id` is the `jti`, and `expires_at` is the expiry time. The replay operation returns `True` for first use and `False` if the token has already been recorded.

| Outcome | Meaning |
|---|---|
| `VALID` | The token passed the implemented checks and is accompanied by verified information |
| `INVALID_SIGNATURE` | The signature is invalid |
| `EXPIRED` | The token has expired |
| `REPLAYED` | The token has already been used within the same replay guard’s scope |
| `MALFORMED` | The structure or data types are invalid, or the issuer is untrusted; an issuer mismatch includes the detail `UNTRUSTED_ISSUER` |
| `WRONG_AUDIENCE` | The token is not intended for the validating station |
| `UNKNOWN_KEY` | The token refers to a public key that is not available to the validator |
| `CLOCK_UNRELIABLE` | The validation time is unsuitable: it precedes issuance or lacks timezone information in the simulation |

A replay-state access failure raises `StorageError` rather than returning `VALID`. This follows the **fail-closed** principle: a token is not accepted when safe verification cannot be completed. The coordinating layer must handle this error by stopping access processing.

Separating these interfaces keeps token verification and usage-state management as distinct responsibilities. An in-memory store can therefore be replaced with persistent storage without changing the validation interface. Raw QR contents must not be logged; monitoring should use outcomes and reason codes to avoid retaining another copy of the credential.

### 3.5. Current Simulation Scope

The implementation uses **Ed25519**, an asymmetric digital signature algorithm. Its token format is `base64url(JSON).base64url(signature)`: the first part contains encoded JSON data and the second contains the signature. The signature covers the encoded first part. Base64url is a representation of data, not encryption; someone reading the QR can still inspect its claims.

This two-part format is specific to the simulation. It does not implement **JSON Web Signature (JWS)**, a standard for packaging signed data. The current token must therefore not be presented as an interoperable JWS/JWT token.

Time validation accepts a token only when `iat ≤ now < exp`. For example, a token issued at 08:00:00 and expiring at 08:01:00 may be accepted at 08:00:59 but must be rejected at exactly 08:01:00. If `exp ≤ iat`, the data is invalid. This example assumes that the signature and all other checks succeed.

The replay store currently resides in the memory of a single running object. A synchronization lock protects the check-and-record operation against concurrent calls. A successfully validated token is recorded before access policy evaluation. Consequently, a subsequent policy denial or gate failure does not make the token reusable within the same store. This business rule must be confirmed when integrating the complete flow.

Public keys and the expected issuer are supplied when the validator is constructed. For example, `PublicKeyQrValidator(public_keys, replay_guard, trusted_issuer="synthetic-hub")` trusts that exact issuer name with the supplied keys. The expected issuer comes from local configuration, never from the scanned token. A missing expected issuer raises `QrError` for a correctly signed token, preventing acceptance without issuer verification. Missing or incorrectly typed `iss` claims are rejected as `MALFORMED`; a correctly signed token from another issuer is rejected as `MALFORMED` with detail `UNTRUSTED_ISSUER`. These checks run before replay state is consumed. Automatic key retrieval from the Hub is not implemented. Private keys are generated temporarily in test memory solely to create signed test inputs; they are neither stored in source code nor provided to the operational Edge.

### 3.6. QR Scenarios and Verification Criteria

Unit tests examine an isolated component using controlled inputs. Integration tests examine collaboration between components, such as validating a QR code and deciding whether to call the gate controller.

| ID | Scenario | Expected Outcome | Current Evidence |
|---|---|---|---|
| QR-01 | A correctly signed token is scanned at issuance or before expiry | Valid result with verified information | Unit tests passed |
| QR-02 | A token is scanned at or after expiry | `EXPIRED`, without verified credential information | Unit tests passed |
| QR-03 | The token’s signature is modified | `INVALID_SIGNATURE`; no usage entry is consumed; the correctly signed token remains usable afterwards | Unit test passed |
| QR-04 | Sixteen concurrent calls use the same token and store | Exactly one valid result and fifteen replay rejections | Unit test passed |
| QR-05 | The intended destination does not match the station | `WRONG_AUDIENCE` | Unit test passed |
| QR-06 | The key identifier is absent from the local trusted-key mapping | `UNKNOWN_KEY` | Unit test passed |
| QR-07 | Invalid encoding, an empty token identifier, an invalid time type, or expiry not later than issuance | `MALFORMED` | Unit tests passed |
| QR-08 | Validation precedes issuance or uses a time without timezone information | `CLOCK_UNRELIABLE` | Unit tests passed |
| QR-09 | The replay store fails | A storage error is raised; no valid result is returned | Unit test passed |
| QR-10 | A rejected QR enters the complete access flow | No unlock command; an appropriate audit reason is recorded | Integration verification pending |
| QR-11 | A token is reused after restart or at a scanner with another store | Requires persistent or shared replay state | Not guaranteed by the simulation |
| QR-12 | A correctly signed token names an issuer other than the locally trusted issuer | `MALFORMED` with `UNTRUSTED_ISSUER`; no replay state is consumed | Unit test passed |
| QR-13 | The issuer claim is absent, empty, or incorrectly typed | `MALFORMED`, without verified information | Unit tests passed |
| QR-14 | The issuer claim is modified without generating a new signature | `INVALID_SIGNATURE`; no replay state is consumed | Unit test passed |
| QR-15 | The expected issuer is missing or invalid in validator configuration | Missing configuration raises `QrError` for a correctly signed token; a blank or non-string value is rejected during construction | Unit tests passed |

## 4. Test Results and Implementation Limitations

The QR test suite contains **30 passing cases**, covering valid credentials, invalid signatures, expiry, concurrent replay, incorrect destinations, unknown keys, malformed data, unsuitable validation times, replay-store failures, and issuer validation and configuration failures. Some scenario groups run with multiple input sets, so the number of executed test cases exceeds the number of scenario rows.

These results establish the tested behaviour of the validator and local replay store. They do not demonstrate the correctness of complete gate control, attendance persistence, or synchronization. The remaining implementation limitations are:

| Limitation | Impact and Required Extension |
|---|---|
| No JWS format | The interoperable token format must be defined before integration with a credential issuance service; issuer checking is implemented, but the operational issuer name and its trusted keys still require configuration |
| No maximum token lifetime enforcement | The simulation checks `exp` but does not cap `exp - iat`. The intended 30–60-second lifetime must be resolved into a precise limit and tested separately |
| No clock-skew tolerance | The current tolerance is zero. An acceptable time difference between Hub and Edge must be defined and clock health monitored; existing time rejection checks do not replace this mechanism |
| No key lifecycle management | Key distribution, replacement, revocation, and the period during which an offline station may retain an old key must be addressed |
| Replay state exists only in memory | Restart can erase usage state, and another station with an independent store may accept the same token |
| Complete-flow verification is pending | Rejected QR inputs must be tested against gate calls, audit recording, and the connectivity-loss scenarios |
| Performance has not been measured | There is no benchmark evidence for the sub-50-millisecond validation target or the 2-second station response requirement under the specified workload |

Hub-side issuance and signing, the complete claim set, the exact validity period, clock tolerance, and the scope of shared replay state remain design details requiring agreement before a complete implementation. These limitations distinguish the tested simulation from the guarantees still required for an operational system.

## 5. AI Tool Usage Declaration

**Nguyen Nhat Hieu — Issue Analysis and QR Validation**

1. **AI tools used:** OpenAI Codex.
2. **Purpose:** To assist with implementing QR validation and replay protection through the agreed interfaces, writing and running unit tests, debugging implementation issues, and checking code behaviour against the requirements.
3. **Main prompts/requests:**

   - Compare the functional and non-functional requirements with the two identified issues, and describe connectivity-loss, expired-QR, and replay scenarios with clear verification criteria.
   - Assist with implementing QR validation through the agreed interface, including signature verification, expiry checks, and feasible replay protection, without changing other components’ contracts.
   - Develop unit tests for valid and rejected credentials, run the tests, and explain failures or environment problems that prevent verification.
   - Explain the replay-store failure and timezone-related test cases, and distinguish verified QR behaviour from access and offline scenarios that remain unimplemented.
   - Prepare and revise a standalone English report section that explains the implementation, test evidence, technical terms, and remaining limitations.

4. **AI-assisted content/outputs:** QR validator and in-memory replay-guard implementation, unit test code, and test execution and troubleshooting. AI assistance does not establish that the complete access control system meets all requirements; verification claims are limited to the tests actually executed and the scope described in this report. I remain responsible for reviewing the AI-assisted material and the final submission.
