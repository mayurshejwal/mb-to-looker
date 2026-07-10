connection: "bigquery"

include: "/views/*.view.lkml"

datagroup: default_datagroup {
  sql_trigger: SELECT CURRENT_DATE() ;;
  max_cache_age: "24 hours"
}

persist_with: default_datagroup

explore: accounts {
}

explore: age_specific_fertility_rates {
}

explore: analytics_events {
}

explore: birth_death_growth_rates {
}

explore: country_names_area {
}

explore: credits {
}

explore: diplomats {
}

explore: embassies {
}

explore: feedback {
}

explore: international_agreement {
}

explore: invoices {
}

explore: midyear_population {
}

explore: midyear_population_5yr_age_sex {
}

explore: midyear_population_age_sex {
}

explore: midyear_population_agespecific {
}

explore: mortality_life_expectancy {
}

explore: movies_data {
}

explore: orders {
}

explore: people {
}

explore: poc_data {
}

explore: products {
}

explore: reviews {
}

explore: visa_app {
}
