# Certificate configuration save behavior

Save errors remain visible beside the Save button and survive periodic status refreshes. The form explicitly reports invalid controls rather than relying on a browser validation bubble. Draft values remain in memory after a rejected or unconfirmed save. Save does not request a certificate or authorize the vault.

The server acknowledges the normalized configuration after reading it back from persistent JSON. A subsequent health/status error is a warning, not a false failed write. A settings write failure restores the previous generated ACME configuration. Old in-flight polls are ignored during a save; polling does not clear action errors. Requests have bounded client-side waits and describe uncertainty on timeout.

Regression coverage uses a loopback-only temporary fixture with the real normalization/save backend. It exercises DNS, HTTP and TLS-ALPN saves, canonical readback, reloads, invalid fields, rejected writes, retained draft values, retries, malformed acknowledgements, diagnostic failures, and visible feedback across viewport sizes. It never accesses production credentials or issues certificates.
