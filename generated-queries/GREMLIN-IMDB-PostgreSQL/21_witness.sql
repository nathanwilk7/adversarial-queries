SET join_collapse_limit = 1;
SELECT count(*)
FROM (((movie_companies CROSS JOIN (((title CROSS JOIN cast_info) CROSS JOIN movie_link) CROSS JOIN name)) CROSS JOIN company_type) CROSS JOIN aka_name) CROSS JOIN movie_keyword
WHERE company_type.kind = 'production companies'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
