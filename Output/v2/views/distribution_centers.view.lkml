view: distribution_centers {
  sql_table_name: `bigquery-public-data.thelook_ecommerce.distribution_centers` ;;

  dimension: id {
    label: "Distribution Center ID"
    description: "Unique identifier for each distribution center."
    primary_key: yes
    type: number
    sql: ${TABLE}.id ;;
  }

  dimension: name {
    label: "Distribution Center Name"
    description: "Name of the distribution center."
    type: string
    sql: ${TABLE}.name ;;
  }

  dimension: latitude {
    type: number
    sql: ${TABLE}.latitude ;;
    label: "Latitude"
    description: "Latitude of the distribution center."
  }

  dimension: longitude {
    type: number
    sql: ${TABLE}.longitude ;;
    label: "Longitude"
    description: "Longitude of the distribution center."
  }

  measure: count {
    drill_fields: [id, name]
    description: "The total number of distribution centers."
    label: "Count of Distribution Centers"
    type: count
  }

}