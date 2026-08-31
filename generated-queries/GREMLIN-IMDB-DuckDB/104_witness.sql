SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((aka_title CROSS JOIN cast_info) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN keyword) CROSS JOIN company_name) CROSS JOIN person_info
WHERE cast_info.nr_order = 7
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
