SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((char_name CROSS JOIN movie_link) CROSS JOIN cast_info) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_keyword) CROSS JOIN kind_type) CROSS JOIN company_type) CROSS JOIN keyword
WHERE char_name.imdb_index = 'II'
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
