# Synthetic PDF fixture source

`synthetic.py` generates invented statements into memory with ReportLab. No bank document, personal data or binary PDF is committed. Two pages contain a purchase with a wrapped description, refund and deposit, repeated headers, count and exact statement totals. Tests mutate the source lines to model omissions/ambiguity and generate an image-only page separately.

To preview outside the repository (test dependency `reportlab==4.4.9`):

```python
import runpy
from pathlib import Path
fixture = runpy.run_path("fixtures/pdf/synthetic.py")
Path("/tmp/perfin-synthetic.pdf").write_bytes(fixture["pdf_bytes"]())
```

The production importer supports this declared synthetic layout only. This is not evidence of any institution's statement support.
