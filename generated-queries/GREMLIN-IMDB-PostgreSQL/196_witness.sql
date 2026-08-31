SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN company_type) CROSS JOIN movie_info) CROSS JOIN cast_info) CROSS JOIN name
WHERE company_type.kind = 'special effects companies'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
