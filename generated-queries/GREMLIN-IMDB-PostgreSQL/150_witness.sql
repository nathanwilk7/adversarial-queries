SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((movie_companies CROSS JOIN (title CROSS JOIN movie_link)) CROSS JOIN aka_title) CROSS JOIN movie_info) CROSS JOIN company_type) CROSS JOIN info_type) CROSS JOIN role_type) CROSS JOIN cast_info) CROSS JOIN person_info) CROSS JOIN movie_keyword
WHERE aka_title.title = 'Anonima ricatti'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id;
