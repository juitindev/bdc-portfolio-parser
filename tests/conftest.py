"""Shared pytest fixtures."""
import pytest


@pytest.fixture
def fdus_rate_strings():
    """Representative FDUS Schedule-of-Investments rate strings."""
    return [
        ("(S+7.75%) / (2.00%)", "11.71%/0.50%"),     # full floating, SOFR
        ("(P+5.00%) / (1.50%)", "10.00%/0.00%"),     # Prime
        ("(S+6.50%)", "10.00%/0.00%"),               # no floor
        ("", "11.00%"),                              # fixed rate
        ("", ""),                                    # equity, no rate
        ("—", "—"),                                  # em-dash null
    ]


@pytest.fixture
def fdus_schedule_html():
    """Minimal HTML mimicking the FDUS Schedule of Investments structure."""
    return """
    <html><body>
    <table>
        <tr><td>Portfolio Company (a)(b)</td><td>Industry</td>
            <td>Variable Index Spread / Floor</td><td>Rate Cash/PIK</td></tr>
        <tr><td>Investment Type</td><td></td><td></td><td></td></tr>
        <tr><td>Control Investments (t)</td></tr>
        <tr><td>Acme Corp</td><td>Manufacturing</td></tr>
        <tr><td>First Lien Debt</td><td>(S+7.75%) / (2.00%)</td>
            <td>11.71%/0.50%</td><td>1/15/2024</td><td>1/15/2029</td>
            <td>$</td><td>1,000</td><td>$</td><td>990</td><td>$</td><td>1,050</td></tr>
        <tr><td>First Lien Debt</td><td>(S+7.50%) / (2.00%)</td>
            <td>11.50%/0.50%</td><td>2/15/2024</td><td>1/15/2029</td>
            <td>$</td><td>500</td><td>$</td><td>495</td><td>$</td><td>520</td></tr>
        <tr><td>First Lien Debt</td><td>(S+8.00%) / (2.00%)</td>
            <td>12.00%/0.50%</td><td>3/15/2024</td><td>1/15/2029</td>
            <td>$</td><td>200</td><td>$</td><td>198</td><td>$</td><td>205</td></tr>
    </table>
    </body></html>
    """
