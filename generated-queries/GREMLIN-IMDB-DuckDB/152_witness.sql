SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((((char_name CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN role_type) CROSS JOIN kind_type) CROSS JOIN movie_info) CROSS JOIN company_name) CROSS JOIN info_type) CROSS JOIN person_info) CROSS JOIN link_type) CROSS JOIN cast_info
WHERE info_type.info = 'LD production country'
  AND title.production_year < 2003
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND title.kind_id = kind_type.id;
