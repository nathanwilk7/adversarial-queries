SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((company_type CROSS JOIN cast_info) CROSS JOIN complete_cast) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN keyword) CROSS JOIN person_info
WHERE company_type.kind = 'production companies'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
