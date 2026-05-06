Feature: Charts and tables
  Vega-Lite-driven charts emitted as vector PATH layers; tables as group
  layers; CSV ingest with formula-injection sanitization; brand-kit
  palette inheritance.

  See ../12-charts.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a Page on a Document with brand_kit "Acme"

  @p0 @critical
  Scenario Outline: Each ChartKind constructs a valid Vega-Lite spec
    When I chart kind=<kind> with valid data, encoding, style
    Then a PATH shape layer is added to the page
    And the underlying Vega-Lite spec validates against vl-convert

    Examples:
      | kind          |
      | BAR           |
      | COLUMN        |
      | STACKED_BAR   |
      | LINE          |
      | AREA          |
      | PIE           |
      | DONUT         |
      | SCATTER       |
      | HEATMAP       |

  @p0
  Scenario: Brand-kit palette is auto-applied
    Given a Document with brand_kit defined and a chart with no explicit palette
    When chart renders
    Then the rendered SVG uses brand_kit palette colours

  @p0 @critical
  Scenario: Empty data renders axes only with "No data"
    Given chart kind=BAR with empty rows
    When chart renders
    Then the result includes "No data" centred
    And no error is raised

  @p0
  Scenario: Single data point in line chart renders as point
    Given chart kind=LINE with rows=[{x:1, y:5}]
    When chart renders
    Then a point marker is rendered
    And a warning is emitted

  @p0
  Scenario: Pie chart with only 1 slice fills the circle
    Given chart kind=PIE with one slice
    When chart renders
    Then the result is a full circle
    And a warning is emitted

  @p0
  Scenario: More categories than palette colours cycles palette
    Given chart kind=BAR with 8 categories and a 5-colour brand palette
    When chart renders
    Then categories 6-8 reuse the first 3 palette colours
    And a warning is emitted

  @p0
  Scenario: Encoding field not present in data raises
    Given chart kind=BAR with rows=[{a:1, b:2}]
    And encoding x.field="missing"
    When chart renders
    Then ChartSpecError is raised

  @p0
  Scenario: Negative values in pie chart rejected
    Given chart kind=PIE with rows containing a negative value
    When chart renders
    Then ChartSpecError is raised

  @p0
  Scenario: Quantitative axis with all-zero values auto-scales
    Given chart kind=BAR with rows where y is always 0
    When chart renders
    Then the y-scale defaults to [-1, 1]

  @p0 @security
  Scenario: CSV cell starting with formula characters is sanitized
    Given a CSV cell starting with "=SUM(A1:A2)"
    When the data is loaded
    Then the leading "=" is stripped or escaped
    And the cell content is preserved as text

  @p0 @security
  Scenario: CSV with PII triggers Warden flag
    Given a CSV containing email addresses + SSNs
    When loaded
    Then Warden flags it as PII
    And storage is blocked
    And a clear message instructs the user to redact

  @p0
  Scenario: Table created with columns + rows + style renders as group layer
    Given a TableLayer with 3 columns and 4 rows + style banded_rows=true
    When table renders
    Then a group layer exists with header + cell sub-layers
    And alternate rows have the band_color background

  @p0
  Scenario: Numeric column auto-right-aligned
    Given a TableColumn with type quantitative
    Then the default column alignment is right
    And cells in this column inherit this alignment unless overridden

  @p0 @perf
  Scenario: 1000-row bar chart renders within budget
    Given chart kind=BAR with 1000 rows
    When the chart renders
    Then the call completes in under 500 ms

  @p1
  Scenario: Chart_data_update re-renders without changing style
    Given a chart with style fields set
    When chart_data_update with new rows
    Then the chart re-renders with new data
    And palette/font/axis style are preserved

  @p1
  Scenario: Datetime field with mixed formats parses best-effort
    Given a CSV column with dates "2024-01-01", "01/02/2024", "March 3"
    When loaded
    Then dateutil parses each
    And a warning is emitted noting the mixed formats
