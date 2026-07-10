view: products {
  sql_table_name: `gcp-project-id.e_commerce_insights.products` ;;

  dimension: id {
    label: "ID"
    primary_key: yes
    type: number
    description: "The primary key for each product."
    sql: ${TABLE}.id ;;
  }

  dimension: name {
    description: "The name of the product."
    sql: ${TABLE}.name ;;
    type: string
    label: "Name"
  }

  dimension: cost {
    sql: ${TABLE}.cost ;;
    description: "The cost of the product."
    type: number
    value_format_name: usd
    label: "Cost"
  }

  dimension: category {
    sql: ${TABLE}.category ;;
    description: "The category of the product (e.g., 'electronics', 'apparel')."
    label: "Category"
    type: string
  }

  measure: count {
    type: count
    label: "Count"
    drill_fields: [id, name]
    description: "The total number of products."
  }

  measure: total_cost {
    value_format_name: usd
    label: "Total Cost"
    type: sum
    description: "The total cost of all products."
    sql: ${cost} ;;
  }

  measure: average_cost {
    value_format_name: usd
    label: "Average Cost"
    type: average
    description: "The average cost of all products."
    sql: ${cost} ;;
  }

  measure: min_cost {
    type: min
    value_format_name: usd
    label: "Minimum Cost"
    description: "The minimum cost of all products."
    sql: ${cost} ;;
  }

  measure: max_cost {
    sql: ${cost} ;;
    description: "The maximum cost of all products."
    type: max
    value_format_name: usd
    label: "Maximum Cost"
  }

  measure: median_cost {
    type: median
    value_format_name: usd
    label: "Median Cost"
    sql: ${cost} ;;
    description: "The median cost of all products."
  }

}