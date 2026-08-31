SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((cast_info CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN aka_name) CROSS JOIN name) CROSS JOIN link_type) CROSS JOIN company_name) CROSS JOIN person_info
WHERE cast_info.nr_order > 7
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
