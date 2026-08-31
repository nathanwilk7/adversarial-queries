SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((title CROSS JOIN (movie_companies CROSS JOIN company_name)) CROSS JOIN movie_keyword) CROSS JOIN cast_info) CROSS JOIN keyword) CROSS JOIN name) CROSS JOIN person_info
WHERE cast_info.nr_order = 7
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
