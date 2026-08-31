SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((((company_type CROSS JOIN complete_cast) CROSS JOIN movie_keyword) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN info_type) CROSS JOIN person_info) CROSS JOIN cast_info) CROSS JOIN role_type) CROSS JOIN keyword) CROSS JOIN movie_link) CROSS JOIN name
WHERE info_type.info = 'LD production country'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
