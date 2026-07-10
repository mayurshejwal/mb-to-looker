connection: "gcp-project-id" # Replace with your BigQuery connection name in Looker

include: "/views/*.view.lkml"

explore: orders {
  label: "E-Commerce Insights"
  description: "Analyze orders, products, and user data"

  join: order_items {
    type: left_outer
    sql_on: ${orders.id} = ${order_items.order_id} ;;
    relationship: one_to_many
  }

  join: products {
    type: left_outer
    sql_on: ${order_items.product_id} = ${products.id} ;;
    relationship: many_to_one
  }

  join: users {
    type: left_outer
    sql_on: ${orders.user_id} = ${users.id} ;;
    relationship: many_to_one
  }
}
