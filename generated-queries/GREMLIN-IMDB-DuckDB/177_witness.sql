SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((((movie_companies CROSS JOIN company_name) CROSS JOIN (complete_cast CROSS JOIN movie_keyword)) CROSS JOIN cast_info) CROSS JOIN movie_link) CROSS JOIN role_type) CROSS JOIN person_info) CROSS JOIN name) CROSS JOIN movie_info) CROSS JOIN link_type) CROSS JOIN info_type) CROSS JOIN title) CROSS JOIN keyword
WHERE info_type.info = 'LD production country'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
