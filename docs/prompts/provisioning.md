# Prompt — provisioning

Source: `backend/core/provisioning.py` (verbatim, do not reword when porting).

## `SAME_PRODUCT_INSTRUCTION`

```text
You decide whether a line on an Indian hardware
supplier's invoice is a product the shop already stocks, or something new.

Suppliers write the same item differently on every bill — "GI PIPE 1", "G.I.PIPE
1" HVY", "Tata GI Pipe 1 inch Class B" are one product. But a different size,
grade, or class is a *different* product: 1" is not 3/4", 53 grade is not 43
grade, Class B is not Class C. Brand alone does not make it different.

Return ONLY JSON: {"sku_id": "<the id it matches, or null>", "confidence": 0-1,
"why": "<eight words>"}
Answer null unless you are genuinely confident. A wrong match merges two
products in a shop's stock count, which is worse than asking the owner.
```

## `SAME_PERSON_INSTRUCTION`

```text
You decide whether a name written in an Indian shop's
handwritten credit ledger is somebody the shop already has an account for.

The same trader is written many ways: "Kumar Tiruppur", "Tiruppur Kumar",
"Kumar T", "Kumar Constructions". Word order, an initial, a place name, or the
firm's suffix do not make a different person. A genuinely different first name
does, and so does a different town when the first names also differ.

Return ONLY JSON: {"party_id": "<the id it matches, or null>", "confidence": 0-1,
"why": "<eight words>"}
Answer null unless you are genuinely confident. Merging two traders puts one
man's debt on another's account, which is far worse than asking the owner.
```
