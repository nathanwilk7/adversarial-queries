SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((aka_title CROSS JOIN complete_cast) CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN info_type) CROSS JOIN kind_type) CROSS JOIN company_type) CROSS JOIN person_info) CROSS JOIN name
WHERE info_type.info = 'genres'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
