SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((comp_cast_type CROSS JOIN complete_cast) CROSS JOIN movie_keyword) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN keyword) CROSS JOIN movie_link) CROSS JOIN company_type) CROSS JOIN cast_info) CROSS JOIN link_type) CROSS JOIN name
WHERE comp_cast_type.kind = 'complete+verified'
  AND name.gender = 'm'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
