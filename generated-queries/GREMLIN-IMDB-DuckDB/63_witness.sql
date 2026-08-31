SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((cast_info CROSS JOIN name) CROSS JOIN title) CROSS JOIN aka_name) CROSS JOIN kind_type) CROSS JOIN movie_companies) CROSS JOIN company_type) CROSS JOIN movie_link) CROSS JOIN movie_keyword) CROSS JOIN keyword
WHERE company_type.kind = 'production companies'
  AND kind_type.kind = 'movie'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
