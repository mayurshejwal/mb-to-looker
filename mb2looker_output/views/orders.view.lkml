view: orders {
  sql_table_name: `gcp-project-id.e_commerce_insights.orders` ;;

  dimension: id {
    description: "The primary key for each order."
    label: "ID"
    type: number
    sql: ${TABLE}.id ;;
    primary_key: yes
  }

  dimension: user_id {
    hidden: yes
    sql: ${TABLE}.user_id ;;
    label: "User ID"
    type: number
    description: "The foreign key to the users table."
  }

  dimension: status {
    description: "The status of the order (e.g., 'pending', 'shipped', 'cancelled')."
    type: string
    label: "Status"
    sql: ${TABLE}.status ;;
  }

  dimension_group: created_at {
    timeframes: [raw, date, week, month, quarter, year]
    description: "The timestamp when the order was created."
    type: time
    label: "Created At"
    sql: ${TABLE}.created_at ;;
  }

  measure: count {
    label: "Count"
    type: count
    drill_fields: [id, users.id]
    description: "The total number of orders."
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