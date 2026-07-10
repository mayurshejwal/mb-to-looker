dashboard: e_commerce_insights {
  title: "E-commerce Insights"
  layout: grid
  
  elements: {
    total_orders: {
      title: "Total Orders"
      explore: orders
      type: "single_value"
      fields: [orders.count]
      limit: 500
      width: 4
      height: 2
    }
    total_revenue: {
      title: "Total Revenue"
      explore: order_items
      type: "single_value"
      fields: [order_items.total_sale_price]
      limit: 500
      width: 4
      height: 2
    }
    average_order_value: {
      title: "Average Order Value"
      explore: order_items
      type: "single_value"
      fields: [order_items.average_sale_price]
      limit: 500
      width: 4
      height: 2
    }
    e_commerce_trends: {
      title: "E-commerce trends"
      explore: orders
      type: "looker_line"
      fields: [orders.created_at_month, orders.count, order_items.total_sale_price]
      sorts: ["orders.created_at_month desc"]
      limit: 500
      width: 12
      height: 4
    }
    top_selling_products: {
      title: "Top selling products"
      explore: order_items
      type: "looker_bar"
      fields: [products.name, order_items.total_sale_price]
      sorts: ["order_items.total_sale_price desc"]
      limit: 10
      width: 6
      height: 4
    }
    spend_by_user: {
      title: "Spend by user"
      explore: order_items
      type: "looker_bar"
      fields: [users.name, order_items.total_sale_price]
      sorts: ["order_items.total_sale_price desc"]
      limit: 10
      width: 6
      height: 4
    }
    orders_by_gender: {
      title: "Orders by gender"
      explore: users
      type: "looker_pie"
      fields: [users.gender, users.count]
      limit: 500
      width: 6
      height: 4
    }
    new_users_per_month: {
      title: "New users per month"
      explore: users
      type: "looker_bar"
      fields: [users.created_at_month, users.count]
      sorts: ["users.created_at_month asc"]
      limit: 500
      width: 6
      height: 4
    }
    orders_by_status: {
      title: "Orders by Status"
      explore: orders
      type: "looker_pie"
      fields: [orders.status, orders.count]
      limit: 500
      width: 6
      height: 4
    }
    average_order_value_by_gender: {
      title: "Average order value by gender"
      explore: order_items
      type: "looker_bar"
      fields: [users.gender, order_items.average_sale_price]
      limit: 500
      width: 6
      height: 4
    }
    orders_from_each_traffic_source: {
      title: "Orders from each traffic source"
      explore: orders
      type: "looker_bar"
      fields: [users.traffic_source, orders.count]
      limit: 500
      width: 12
      height: 4
    }
  }
}
