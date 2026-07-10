- dashboard: orders_by_status
  title: "Orders by Status"
  layout: newspaper
  elements:
  - name: orders_by_status_viz
    title: "Orders by Status"
    model: e_commerce_insights
    explore: orders
    type: looker_pie
    fields: [orders.count, orders.status]
    sorts: [orders.count desc]
    limit: 500
    vis_config:
      value_labels: "legend"
      label_type: "labPer"
      pie_hole_radius: 0.35
      series_colors: {}
