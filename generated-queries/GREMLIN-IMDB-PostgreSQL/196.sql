SELECT count(*)
FROM cast_info, company_type, complete_cast, movie_companies, movie_info, movie_link, name, title
WHERE company_type.kind = 'special effects companies'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
