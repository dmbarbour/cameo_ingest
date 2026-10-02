# Research: searching the corpus without tools, 2026-10-02

**Question.** How can people who have only common office tools search the corpus by keyword:
requirement ids, element names, summaries? The tree would be shared through SharePoint. Plan
RE found that embeddings almost never find a requirement by its id, while BM25 finds it nine
times in ten (`retrieval-baseline-2026-10-01.md`). The maintainer's RAG service can't do
keyword search, and they can't run Python or a database where they work.

**Method.** Microsoft's documentation on Excel's limits, Excel for the web, SharePoint
Online's browser file handling, previews and search indexing (sources at the end). The
corpus was measured on plan RA's reference tree (`out/ra/final-llm`: the samples and the
fiction, 26 projects). Nothing was tried on the maintainer's SharePoint, so the plan ends
with a check there.

## The corpus

| What | Count |
|---|---|
| Elements | 191,669 |
| Requirements | 8,801 |
| Relationships | 23,595 |
| Diagrams | 3,642 |
| Identifier records (`index/ids.jsonl`) | 9,605 |
| Chunks (51 MB of text) | 85,298, each a `rag/text` file |
| Pages | 5,461 |

**Path lengths, relative to the tree:**
- `rag/text` files: median 96 characters, at most 121.
- Pages: median 114, 95th percentile 237, at most 240.

## Findings

**Excel.**
- **Grid and cells:** 1,048,576 rows a sheet and 32,767 characters a cell, enough for every
  element.
- **Hyperlinks:**
  - **Hyperlink objects:** at most 65,530 per worksheet, each up to 2,079 characters.
  - **The `HYPERLINK()` function:** limited to 255 characters, but not counted against that
    limit.
- **Search:** desktop Excel searches the whole workbook (Find, Within: Workbook). Whether
  Excel for the web searches beyond the open sheet is not documented, so the design keeps
  everything findable from one sheet.

**Excel for the web, from SharePoint.**
- **Size:** it opens workbooks up to 100 MB (50 MB from OneDrive). Larger ones must be
  downloaded and opened in desktop Excel.
- **Links:** it does not follow relative hyperlinks, so links must be absolute URLs, made from
  the folder's SharePoint address.

**SharePoint Online and HTML.**
- **No in-place pages:** SharePoint Online has no "permissive" file handling, so an HTML file
  is downloaded, not shown, and its scripts don't run in place. A search page would have to be
  downloaded and opened from disk. It would then be a single file, with its data inline,
  since a page opened from disk can't fetch other files.
- **Previews:** SharePoint, OneDrive and Teams preview `.md`, `.txt` and `.html` files in the
  browser. Previews are unlikely to honour a link's `#anchor`; that is untested.

**SharePoint search.**
- **What it indexes:** by default, `.txt`, `.csv`, `.html`, `.xlsx`, `.docx` and `.pdf`, but not
  `.md` or `.json`.
- **How much:** it parses at most 2 million characters of a file, and words from its first
  million. A whole-corpus workbook would be indexed only in part, but each `rag/text` file
  (one chunk) would be indexed whole.
- **Identifiers:** the hyphen breaks words, so `REQ-1-OAD-1050` is indexed as `REQ`, `1`, `OAD`,
  `1050`. A quoted phrase query should still find it. Untested.

**The other options.**
- **TiddlyWiki-like single-file pages:** these have the same download-first constraint. They also
  grow slow past tens of thousands of entries.
- **Obsidian or VS Code:** either opens the tree's pages as they are, Markdown with relative
  links, with no work on our side. Few people have them, so they are worth a paragraph in the
  README, not a format.

## Conclusions

1. **A workbook, `CATALOG.xlsx`, is the primary export.**
   - It opens in Excel for the web from SharePoint while it stays under 100 MB, and in desktop
     Excel either way.
   - One sheet should hold a row for everything worth finding, so that Ctrl+F on that sheet
     finds anything, wherever Find's scope ends.
2. **Links should be absolute, built from a SharePoint base URL** that the maintainer sets as a
   tree setting. Two kinds suit two targets:
   - **Chunk files** (`rag/text/…`, at most 121 characters) take `HYPERLINK()` formulas: short
     enough for 255 characters with a base URL of up to about 130, and not limited per sheet.
     They land on the exact text, which SharePoint previews and indexes.
   - **Pages** (up to 240 characters) need hyperlink objects. There are 5,461 of them, which
     fit one sheet.
3. **SharePoint's own search is a free second route,** if `rag/text` is uploaded with the tree.
   How it treats hyphenated ids needs a test on the maintainer's tenant.
4. **A single-file HTML search page waits.** It is worth building only if the workbook falls
   short.

## After the maintainer's answers (2026-10-02)

- **No SharePoint addresses for now.** Links stay relative, and each item shows its source: the
  input path, which mirrors SharePoint's folders, and its `--meta` values. Conclusion 2's
  constraints, on URL length and links per sheet, then matter only once addresses are
  available.
- **Downloading a page and opening it is acceptable, if the page says so.** That makes a static
  page a real option, not a fallback (conclusion 4).
- **Plan KX builds both** from one set of records, and lets a trial decide.

**What each offers beyond Ctrl+F:**
- **Excel** has column filters ("contains", wildcards), and, from Excel 2021 or Microsoft 365
  or on the web, `FILTER` and `SEARCH` formulas, which can list the rows that hold all of the
  words typed into a cell. It has no relevance ranking, no prefix or typo matching, and no
  browsing between related items beyond links between sheets.
- **A page** can rank results (BM25), match prefixes and quoted phrases, and keep ids whole. It
  can filter by project and kind, highlight the words in snippets, and link an item to its
  related items. Its costs:
  - the download step;
  - memory and load time in proportion to the corpus;
  - our JavaScript to maintain, which can be tested with Node here.

## A page opened from disk: what browsers allow (2026-10-02)

**Does work:**
- **Classic scripts:** `<script src="data/x.js">` loads a sibling file from `file://` in
  Chrome, Edge and Firefox. Data can therefore come in script files that assign it, but not
  through `fetch`.
- **Links and images:** relative links and `<img>` work, so a page inside an extracted folder can
  show sketches and open pages.
- **Decompression:** `DecompressionStream("gzip")` is in every current browser (Chrome 80,
  Firefox 113, Safari 16.4; widely available since May 2023). Data can travel gzipped and
  base64-encoded inside the page.
- **Scripts in downloaded files:** a downloaded page still runs its scripts. The Mark of the Web
  restricts Office documents and MHTML, not plain HTML. Policies differ between
  organisations, so the trial checks this.

**Doesn't work:**
- **`fetch` and XHR to sibling files** are blocked: Chrome gives the page the `null` origin, and
  Firefox (since 68) gives each file an origin of its own.
- **ES modules** (`type="module"`) fail from `file://` (CORS).
- **Web workers:** Chrome won't start them from a file. Workers from blob URLs behave
  differently across browsers, so they are not to be relied on. Long work must be cut into
  slices on the main thread, which lets a progress bar repaint between them.
- **Persistent storage:** localStorage and IndexedDB are unreliable for `file://` pages, so the
  page should be fast to rebuild its index each time rather than cache it.

**Zip files on Windows:** double-clicking an HTML file inside a zip, in Explorer's preview,
extracts that file alone into a temporary folder, and its relative links and scripts break.
People must use "Extract All" first. A page can detect that it was opened from such a
temporary folder and say so.

**SharePoint downloads:** a folder download is zipped on the fly, but limited to 10,000 files.
`rag/text` alone has 85,298, so a bundle must be shipped as one zip file of our own.

**Sizes** on plan RA's reference tree:

| What | Size |
|---|---|
| All chunk text | 52 MB, 5.4 MB gzipped (≈7.2 MB as base64 in a page) |
| Sketches (3,697 PNG) | 43 MB, already compressed |
| Pages (5,461 Markdown) | 108 MB |

**What follows:**
- **A single self-contained page holds the whole corpus's text in about 8 MB.** Download speed
  and file size stop being a concern; load time is mostly decompression, parsing and building
  the index, which can be measured and shown with progress.
- **A bundle zip adds what doesn't embed cheaply, the sketches, and the pages if they are
  wanted.** The page can find out whether the bundle is there by loading a small script beside
  it, which fails if the file is missing.

**More sources:**
- [Loading module scripts from `file://` (WHATWG issue 8121)](https://github.com/whatwg/html/issues/8121)
- [Firefox 68: local files get their own origin](https://www.statsilk.com/support/running-offline-javascript-firefox-68-resolving-cross-origin-request-blocked)
- [Not allowed to load local resource (blob URL), Chromium issue 366055344](https://issues.chromium.org/issues/366055344)
- [Compression Streams are now supported on all browsers](https://web.dev/blog/compressionstreams)
- [Download files and folders from OneDrive or SharePoint (limits)](https://support.microsoft.com/en-us/onedrive/download-files-and-folders-from-onedrive-or-sharepoint)
- [Warning users about the Windows Explorer zip archive preview (Ben Nadel)](https://www.bennadel.com/blog/4138-warning-users-about-the-windows-explorer-zip-archive-preview-in-javascript.htm)
- [Mark of the Web](https://en.wikipedia.org/wiki/Mark_of_the_Web)

## Sources

- [Excel specifications and limits](https://support.microsoft.com/en-us/excel/excel-specifications-and-limits)
- [File size limits for workbooks in SharePoint](https://support.microsoft.com/en-us/office/file-size-limits-for-workbooks-in-sharepoint-9e5bc6f8-018f-415a-b890-5452687b325e)
- [Excel hyperlinks to SharePoint documents not working (relative links)](https://learn.microsoft.com/en-us/answers/questions/644195/excel-hyperlinks-to-sharepoint-documents-not-worki)
- [Open HTML files in browser instead of prompting for download (SharePoint Online)](https://learn.microsoft.com/en-us/archive/msdn-technet-forums/cac39f11-9931-4163-9d48-7244a24dbafc)
- [File types supported for previewing files in OneDrive, SharePoint, and Teams](https://support.microsoft.com/en-us/onedrive/file-types-supported-for-previewing-files-in-onedrive-sharepoint-and-teams)
- [Default crawled file name extensions and parsed file types](https://learn.microsoft.com/en-us/sharepoint/technical-reference/default-crawled-file-name-extensions-and-parsed-file-types)
- [Search limits for SharePoint](https://learn.microsoft.com/en-us/sharepoint/search-limits)
- [Extended word breaking for search in SharePoint Online](https://learn.microsoft.com/en-us/archive/blogs/beyondsharepoint/search-extended-word-breaking)
- [XlsxWriter: the Worksheet class (`write_url` limits)](https://xlsxwriter.readthedocs.io/worksheet.html)
- [XlsxWriter: the Workbook class (`constant_memory`)](https://xlsxwriter.readthedocs.io/workbook.html)
