# Sample recordings

Publicly available screen recordings to feed the observer. All are YouTube
uploads under the YouTube standard licence: fine for a hackathon demo, not for
redistribution. Raw downloads, captions and contact sheets are in `raw/` and
`sheets/`. Re-download with `yt-dlp` using the IDs below.

## sap_b1_create_sales_order_demo.mp4  (recommended, 118 s)

- Source: NavigatorSAP, "Create Sales Order | Examples and How-To | SAP Business One",
  https://www.youtube.com/watch?v=SatDb9sLydE (2:50, 1280x694, narrated).
- Cut 0:10 to 2:08 of the original, audio loudness-normalised (original was very quiet).
- Genuine full-screen recording of the SAP Business One desktop client. No slides,
  no presenter. Exactly the "thick client, no DOM" case Scribe and Tango cannot capture.
- `sap_b1_create_sales_order_full.mp4` is the normalised full video, which also
  contains a second task (create order from a quotation, 2:10 to 2:30).

Ground truth steps, timestamps relative to the original (subtract 10 s for the demo cut):

| # | t (orig) | action | target / value |
|---|---------|--------|----------------|
| 1 | 0:11 | navigate | Modules > Sales A/R > Sales Order |
| 2 | 0:16 | click | Sales Order (opens blank form) |
| 3 | 0:38 | type | Customer field |
| 4 | 0:41 | type | Tab key, choose customer from list |
| 5 | 0:47 | verify | Logistics tab: ship-to and bill-to auto-filled |
| 6 | 0:55 | verify | Sales Employee defaulted |
| 7 | 1:06 | click | Contents tab |
| 8 | 1:13 | select | Items via Shift (range) or Ctrl (pick) in the item list |
| 9 | 1:28 | verify | Quantity, unit price, in stock, tax code, warehouse |
| 10 | 1:51 | click | Add (fails: delivery date required) |
| 11 | 1:56 | type | Delivery Date = 30th |
| 12 | 1:59 | click | Update rows |
| 13 | 2:01 | click | Add |
| 14 | 2:06 | verify | Created sales order displayed |

Step 10 is a natural "expected failure" the observer should capture as a pitfall.

## google_ai_studio_api_key_screen_only.mp4  (partner, 51 s)

- Source: Google Cloud, "Get Your Gemini API Key in Google AI Studio EASY Tutorial",
  https://www.youtube.com/watch?v=JdKcFCLotZY (1:33). Presenter is Paige Bailey,
  Engineering Lead for DevRel at Google DeepMind.
- Cut 0:14.6 to 1:06 of the original: the screen-recording segment with the
  presenter in a picture-in-picture inset. The full video is talking head before
  and after, useful as a noise-collapse test if you want it (`raw/JdKcFCLotZY.mp4`).

Ground truth steps (original timestamps):

| # | t (orig) | action | target |
|---|---------|--------|--------|
| 1 | 0:22 | navigate | aistudio.google.com |
| 2 | 0:26 | click | "Get API key" button, top bar |
| 3 | 0:30 | click | "Create API key" |
| 4 | 0:33 | select | Cloud project |
| 5 | 0:38 | verify | Key generated dialog, Copy button |
| 6 | 0:45 | verify | API keys list, per-project usage |
| 7 | 0:55 | verify | Dashboard usage charts |

Short and simple. Good as the second demo, weak as the primary because the
inset presenter occupies part of every frame.

## Rejected

- SAP PRESS "How to Create a Sales Order with SAP Fiori in SAP S/4HANA"
  (SLX9lr1YJVA, 1:30): produced explainer, small inset screenshots on a blue
  background, mixes SAP GUI and Fiori. Keep only as a stress test.
- SAP Business One official "Starting with SAP Business One, Web client"
  (oJtiUHjbA1E, 5:24): a feature tour, not a single task.
- Modal and Pydantic channels: talks and long tutorials, no short UI task
  recordings. Conduct has no public product video.
