SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((aka_title CROSS JOIN complete_cast) CROSS JOIN cast_info) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN name) CROSS JOIN person_info) CROSS JOIN company_name) CROSS JOIN movie_link
WHERE aka_title.production_year < 2016
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
