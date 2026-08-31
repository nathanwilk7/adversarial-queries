SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((((aka_title CROSS JOIN movie_keyword) CROSS JOIN movie_link) CROSS JOIN link_type) CROSS JOIN title) CROSS JOIN char_name) CROSS JOIN kind_type) CROSS JOIN cast_info) CROSS JOIN role_type) CROSS JOIN keyword) CROSS JOIN movie_companies) CROSS JOIN company_type
WHERE char_name.imdb_index = 'II'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
