# Riftbound K/DA – Beta (payment-safe)

This is a **test prototype**, not a production 24/7 stock monitor. It does **not** submit an order, pay, or handle SMS codes. Product discovery is best-effort and does **not** yet determine real stock/variant IDs; it reports `UNKNOWN` until a reliable data source is integrated. No fictitious variant is inserted.

## Windows quick start

```powershell
py -m pip install -r requirements.txt
py -m playwright install chromium
py -m unittest discover -s tests -v
py bot.py --mode fixture
py bot.py --mode live --pages 3
```

## Verify a real Shopify cart permalink

Find the **actual variant ID** for an eligible product from the store (never use a made-up ID). Then:

```powershell
py bot.py --mode fixture --variant-id 123456789
```

This prints a **test-only** cart permalink with the Bielefeld address prefill (replace `123456789` with the actual ID). Paste that link into your **phone's** browser and check the item, Riot sign-in, German shipping address, EUR subtotal, shipping and final total. Shopify supports checkout `shipping_address` prefill parameters, but Riot may not honor them. Do not confirm a real payment during the beta.

For an optional WhatsApp preview, configure the following **locally as environment variables or GitHub encrypted secrets**: `GREEN_API_INSTANCE`, `GREEN_API_TOKEN`, `GREEN_API_URL`, `WHATSAPP_CHAT_ID`. Never commit credentials. Then use `--send-whatsapp` with a **verified** variant ID. GREEN-API endpoint requirements should be checked with your instance configuration.

## Beta case matrix

| Case | Expected behavior | Automated? |
|---|---|---|
| `K/DA Bundle` | Matches | Yes (unit test) |
| `K/DA Paket` | Matches | Yes (unit test) |
| K/DA poster only | Excluded | Yes (unit test) |
| Other Riftbound Bundle | Excluded | Yes (unit test) |
| Non-numeric variant ID | Rejected | Yes (unit test) |
| One-item checkout link + Germany address | Proper URL parameters | Yes (unit test) |
| Riot TR account signs into DE checkout | No region restriction | **Manual test needed** |
| Delivery to Bielefeld 33609 | Address/shipping accepted | **Manual test needed** |
| EUR price + shipping | Total visible | **Manual test needed** |
| Akbank / Google Pay | Method offered, no payment | **Manual test needed** |
| WhatsApp receipt | Preview received | Manual integration test |

**Known constraints:** On actual Riot pages products may be rendered inside a client app and `a[href*=\"/product/\"]` detection may fail. This beta will surface misses instead of claiming full coverage. Cart permalink support, Riot ID eligibility, and German delivery must be verified in a real session. Never send 3DS codes to the bot.

Sources:
- https://shopify.dev/docs/apps/build/checkout/create-cart-permalinks
- https://merch.riotgames.com/de-de/shipping/
