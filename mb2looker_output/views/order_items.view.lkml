view: order_items {
  sql_table_name: `gcp-project-id.e_commerce_insights.order_items` ;;

  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
    label: "ID"
    description: "The primary key for each order item."
    primary_key: yes
  }

  dimension: order_id {
    type: number
    sql: ${TABLE}.order_id ;;
    description: "The foreign key to the orders table."
    label: "Order ID"
    hidden: yes
  }

  dimension: product_id {
    type: number
    sql: ${TABLE}.product_id ;;
    description: "The foreign key to the products table."
    label: "Product ID"
    hidden: yes
  }

  dimension: sale_price {
    value_format_name: usd
    type: number
    label: "Sale Price"
    description: "The price at which the product was sold."
    sql: ${TABLE}.sale_price ;;
  }

  measure: count {
    type: count
    description: "The total number of order items."
    label: "Count"
    drill_fields: [id]
  }

  measure: total_sale_price {
    type: sum
    label: "Total Sale Price"
    description: "The total sale price of all order items."
    sql: ${sale_price} ;;
    value_format_name: usd
  }

  measure: average_sale_price {
    value_format_name: usd
    type: average
    label: "Average Sale Price"
    description: "The average sale price of all order items."
    sql: ${sale_price} ;;
  }

  measure: min_sale_price {
    value_format_name: usd
    type: min
    label: "Minimum Sale Price"
    description: "The minimum sale price of all order items."
    sql: ${sale_price} ;;
  }

  measure: max_sale_price {
    type: max
    label: "Maximum Sale Price"
    description: "The maximum sale price of all order items."
    sql: ${sale_price} ;;
    value_format_name: usd
  }

  measure: median_sale_price {
    value_format_name: usd
    type: median
    label: "Median Sale Price"
    description: "The median sale price of all order items."
    sql: ${sale_price} ;;
  }

}