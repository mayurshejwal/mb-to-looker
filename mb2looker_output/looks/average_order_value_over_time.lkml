- dashboard: average_order_value_over_time
  title: "Average Order Value over Time"
  layout: newspaper
  elements:
  - name: average_order_value_over_time_viz
    title: "Average Order Value over Time"
    model: e_commerce_insights
    explore: orders
    type: looker_line
    fields: [order_items.average_sale_price, orders.created_at_month]
    sorts: [orders.created_at_month asc]
    limit: 500
    vis_config:
      show_value_labels: false
      legend_position: "center"
      x_axis_gridlines: false
      y_axis_gridlines: true
      show_view_names: false
      point_style: "none"
      series_colors: {}
      show_x_axis_label: true
      show_x_axis_ticks: true
      show_y_axis_labels: true
      show_y_axis_ticks: true
      x_axis_scale: "auto"
      y_axis_scale_mode: "linear"
