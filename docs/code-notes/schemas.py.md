# app/schemas.py

## 1. Purpose
Defines the shape of the JSON the API accepts and returns.

## 2. Why it exists
FastAPI uses these classes to validate incoming data automatically and to produce consistent responses.

## 3. Important functions/classes
- **`RegistrationRequest`** — input body: `student_id` (text, e.g. `"STU001"`) and `section_id` (integer).
  A wrong type or missing field is rejected by FastAPI with HTTP 422 before our code runs.
- **`RegistrationResponse`** — output body: `success` (true/false) and `message` (human-readable text).

## 4. Important variables
- `student_id` — identifies the student attempting registration.
- `section_id` — identifies the course section whose seat allocation is processed.

## 5. Execution flow
`main.py` receives a `RegistrationRequest`, calls the service, and returns a `RegistrationResponse`.

## 6. Database behavior
None.

## 7. Error handling
Malformed JSON bodies get FastAPI's automatic 422 response.

## 8. Testing
`test_api.py` checks the exact response bodies.
