SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((title CROSS JOIN company_type) CROSS JOIN name) CROSS JOIN link_type) CROSS JOIN movie_link) CROSS JOIN cast_info) CROSS JOIN movie_companies
WHERE company_type.kind = 'production companies'
  AND name.imdb_index = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
