SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((cast_info CROSS JOIN complete_cast) CROSS JOIN movie_link) CROSS JOIN name) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN link_type) CROSS JOIN company_type) CROSS JOIN movie_keyword) CROSS JOIN aka_name) CROSS JOIN keyword
WHERE company_type.kind = 'production companies'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
