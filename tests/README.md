# Tests

Test layers:

- Governance/contract/unit tests without model or network.
- Component and integration tests with fake or recorded fixtures.
- E2E, replay, performance, soak, chaos and security gates added by their owning modules.

A bug found at a high layer should become a deterministic regression at the lowest useful layer.
