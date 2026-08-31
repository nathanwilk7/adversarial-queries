SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((title CROSS JOIN aka_title) CROSS JOIN movie_companies) CROSS JOIN link_type) CROSS JOIN cast_info) CROSS JOIN char_name) CROSS JOIN company_type) CROSS JOIN movie_link
WHERE char_name.imdb_index = ''
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
