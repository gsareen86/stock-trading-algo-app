# platform-api

## ADDED Requirements

### Requirement: The root path identifies the service
`GET /` MUST answer successfully with the service identity and the paths of its real
endpoints, rather than a 404.

#### Scenario: Root answers rather than 404
- GIVEN the API is running
- WHEN `GET /` is requested
- THEN the response is 200

#### Scenario: Root names where to go next
- GIVEN a response from `GET /`
- WHEN it is read
- THEN it names the interactive documentation path
- AND lists the platform's endpoints

#### Scenario: Root does not duplicate the health report
- GIVEN a response from `GET /`
- WHEN it is read
- THEN it carries no seam status
- AND health remains the single answer to whether the platform is up
