import unittest

from electricity_monitor.mymeter import _browser_fetch_headers


class BrowserFetchHeaderTests(unittest.TestCase):
    def test_removes_headers_fetch_cannot_set(self):
        headers = {
            "Accept": "text/csv",
            "Cookie": "session=secret",
            "Host": "mysmartenergy.psegliny.com",
            "Origin": "https://mysmartenergy.psegliny.com",
            "Referer": "https://mysmartenergy.psegliny.com/Usage",
            "User-Agent": "Captured Browser",
            "X-Requested-With": "XMLHttpRequest",
        }

        self.assertEqual(
            _browser_fetch_headers(headers),
            {
                "Accept": "text/csv",
                "X-Requested-With": "XMLHttpRequest",
            },
        )


if __name__ == "__main__":
    unittest.main()
