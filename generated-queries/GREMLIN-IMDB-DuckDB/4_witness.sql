SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((cast_info CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_keyword) CROSS JOIN keyword) CROSS JOIN company_type) CROSS JOIN name) CROSS JOIN aka_name
WHERE cast_info.nr_order < 10
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
