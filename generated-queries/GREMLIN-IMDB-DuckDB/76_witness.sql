SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((cast_info CROSS JOIN role_type) CROSS JOIN company_type) CROSS JOIN aka_name) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN name) CROSS JOIN movie_keyword) CROSS JOIN keyword
WHERE company_type.kind = 'production companies'
  AND movie_info.info = 'Color'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id;
