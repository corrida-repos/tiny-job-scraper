# Company report logos

These PNGs were retrieved from the 56 active employers' official websites on
22 October 2026. Most use the site's published app/favicons; Intellias and
Zühlke use published inline brand artwork. Exact source URLs are recorded in
[company-logos.json](../../config/company-logos.json).

The report shows a small logo beside each company heading. Gmail delivery embeds
only the logos used in that report as inline PNG MIME parts. It does not query a
logo provider or download images at send time. Markdown uses the versioned public
repository asset URLs. If an asset is unavailable, the company name still appears.

Source images were converted to PNG during asset preparation. Image-conversion
libraries are not runtime dependencies. Replacing a logo requires updating its
versioned PNG and manifest provenance, without changing job screening.
