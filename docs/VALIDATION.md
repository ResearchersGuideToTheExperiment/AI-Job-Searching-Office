# Release validation

Checked on Windows with Python 3.14.3 on 23 November 2026:

- Automated suite: **126 passed**. Includes fictional vacancy extraction, profile review, approval gates, document generation, worker lifecycle, dashboard pages, renamed input folders, release export, empty first-install defaults, and PDF extraction/limits with pypdf.
- Streamlit HTTP smoke check: loopback health endpoint and dashboard responded successfully; test server stopped afterward.
- Installed dependency consistency: `pip check` reported no broken requirements.
- Release manifest: public text files passed machine-home-path, private-key, and common-token checks, plus a targeted review for identifiers from the removed local records.
- Git ignore checks: 14 representative private paths were ignored, including personal files in both PUT_YOUR folders. The three public folder guide/configuration files remained stageable.
- Fresh dependency installation: all requirements installed into a new Windows virtual environment. The updated lock file records the 58 installed project dependencies; their declared licenses are listed in the dependency inventory.

Model inference and live job-site discovery were not rerun for this release cleanup. Automated tests mock those external responses. The included Windows CI workflow repeats installation and checks on GitHub; it has not been run there yet.

Passing checks do not guarantee model accuracy, future website availability, or that later edits contain no private information. Review changes before publishing each release.
