- dashboard: user_demographics
  title: "User Demographics"
  layout: newspaper
  elements:
  - name: user_demographics_viz
    title: "User Demographics"
    model: e_commerce_insights
    explore: orders # Using orders explore which has a join to users
    type: looker_bar
    fields: [users.count, users.created_at_year, users.state]
    pivots: [users.state]
    sorts: [users.created_at_year asc]
    limit: 500
    vis_config:
      stacking: "normal"
      show_value_labels: false
      legend_position: "center"
      x_axis_gridlines: false
      y_axis_gridlines: true
      show_view_names: false
      series_colors: {}
      show_x_axis_label: true
      show_x_axis_ticks: true
      show_y_axis_labels: true
      show_y_axis_ticks: true
      x_axis_scale: "auto"
      y_axis_scale_mode: "linear"
