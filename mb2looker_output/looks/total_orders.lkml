- dashboard: total_orders
  title: "Total Orders"
  layout: newspaper
  elements:
  - name: total_orders_viz
    title: "Total Orders"
    model: e_commerce_insights
    explore: orders
    type: single_value
    fields: [orders.count]
    limit: 500
    vis_config:
      series_colors: {}
