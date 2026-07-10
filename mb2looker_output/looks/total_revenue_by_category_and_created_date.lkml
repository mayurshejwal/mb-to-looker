dashboard: total_revenue_by_category_and_created_date
title: "Total Revenue by Category and Created Date"
layout: newspaper
elements:
- name: total_revenue_by_category_and_created_date_viz
  title: "Total Revenue by Category and Created Date"
  model: e_commerce_insights
  explore: orders
  type: looker_line
  fields: [order_items.total_sale_price, products.category, orders.created_at_month]
  pivots: [products.category]
  sorts: [orders.created_at_month asc]
  limit: 500
  vis_config:
    stacking: "normal"
    show_value_labels: false
    label_density: 25
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
    y_axis_tick_density: "default"
    y_axis_tick_density_custom: 5
