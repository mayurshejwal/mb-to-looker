view: users {
  sql_table_name: `gcp-project-id.e_commerce_insights.users` ;;

  dimension: id {
    description: "The primary key for each user."
    label: "ID"
    type: number
    sql: ${TABLE}.id ;;
    primary_key: yes
  }

  dimension: name {
    type: string
    sql: ${TABLE}.name ;;
    description: "The full name of the user."
    label: "Name"
  }

  dimension: email {
    label: "Email"
    description: "The email address of the user."
    type: string
    sql: ${TABLE}.email ;;
  }

  dimension: age {
    description: "The age of the user."
    label: "Age"
    type: number
    sql: ${TABLE}.age ;;
  }

  dimension: age_tier {
    tiers: [18, 25, 35, 45, 55, 65]
    type: tier
    sql: ${age} ;;
    label: "Age Tier"
    style: integer
    description: "The age of the user in tiers."
  }

  dimension: city {
    description: "The city where the user resides."
    label: "City"
    type: string
    sql: ${TABLE}.city ;;
  }

  dimension: state {
    description: "The state where the user resides."
    label: "State"
    type: string
    sql: ${TABLE}.state ;;
    map_layer_name: us_states
  }

  dimension: country {
    type: string
    sql: ${TABLE}.country ;;
    description: "The country where the user resides."
    label: "Country"
    map_layer_name: countries
  }

  dimension_group: created_at {
    label: "Created At"
    description: "The timestamp when the user account was created."
    type: time
    sql: ${TABLE}.created_at ;;
    timeframes: [raw, date, week, month, quarter, year]
  }

  dimension: tenure_in_days {
    type: number
    sql: DATE_DIFF(CURRENT_DATE(), DATE(${created_at_date}), DAY) ;;
    description: "The number of days since the user signed up."
    label: "Tenure in Days"
  }

  dimension: tenure_tier {
    type: tier
    sql: ${tenure_in_days} ;;
    label: "Tenure Tier"
    style: integer
    description: "The tenure of the user in tiers."
    tiers: [0, 30, 60, 90, 180, 365]
  }

  measure: count {
    type: count
    drill_fields: [id, name]
    label: "Count"
    description: "The total number of users."
  }

  measure: average_age {
    label: "Average Age"
    description: "The average age of the users."
    type: average
    sql: ${age} ;;
  }

  measure: min_age {
    label: "Minimum Age"
    description: "The minimum age of the users."
    type: min
    sql: ${age} ;;
  }

  measure: max_age {
    type: max
    sql: ${age} ;;
    description: "The maximum age of the users."
    label: "Maximum Age"
  }


  parameter: date_granularity {
    type: unquoted
      allowed_value: { label: "Date" value: "date" }
      allowed_value: { label: "Week" value: "week" }
      allowed_value: { label: "Month" value: "month" }
      allowed_value: { label: "Quarter" value: "quarter" }
      allowed_value: { label: "Year" value: "year" }
    default_value: "month"
  }

  dimension: dynamic_date {
    label: "Date (dynamic)"
    sql:
      {% if date_granularity._parameter_value == 'date' %}${created_at_date}
      {% elsif date_granularity._parameter_value == 'week' %}${created_at_week}
      {% elsif date_granularity._parameter_value == 'month' %}${created_at_month}
      {% elsif date_granularity._parameter_value == 'quarter' %}${created_at_quarter}
      {% elsif date_granularity._parameter_value == 'year' %}${created_at_year}
      {% else %}${created_at_month}
      {% endif %} ;;
  }

}