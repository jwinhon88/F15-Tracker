from app.edgar import parse_information_table_xml


XML = """<?xml version='1.0' encoding='UTF-8'?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>1000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>5000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>5000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>
"""


def test_parse_information_table_xml():
    holdings = parse_information_table_xml(XML)
    assert len(holdings) == 1
    row = holdings[0]
    assert row["issuer"] == "APPLE INC"
    assert row["cusip"] == "037833100"
    assert row["value_usd_000"] == 1000
    assert row["shares"] == 5000
    assert row["voting_sole"] == 5000
