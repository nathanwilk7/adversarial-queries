SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((((aka_title CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_keyword) CROSS JOIN keyword) CROSS JOIN company_name) CROSS JOIN info_type) CROSS JOIN movie_info) CROSS JOIN person_info) CROSS JOIN complete_cast) CROSS JOIN name
WHERE info_type.info = 'LD production country'
  AND name.imdb_index = 'XC'
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
